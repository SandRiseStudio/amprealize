"""Slack sink for log alerting and notifications.

This sink sends log events to Slack channels based on severity thresholds,
enabling real-time alerts for critical events like cost overruns or errors.

Example:
    sink = SlackSink(
        webhook_url="https://hooks.slack.com/services/XXX/YYY/ZZZ",
        channel="#alerts",
        min_level="warning",  # Only send warnings and above
    )

    # Use as an alert sink alongside primary storage
    service = RazeService(
        sink=primary_sink,
        alert_sinks=[sink],  # Separate alert path
    )
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from queue import Queue, Empty

from raze.models import (
    LogAggregateRequest,
    LogAggregation,
    LogEvent,
    LogQueryRequest,
)
from raze.sinks.base import RazeSink

logger = logging.getLogger(__name__)


# Log level ordering for threshold comparison
LOG_LEVEL_PRIORITY = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}


@dataclass
class SlackMessage:
    """Structured Slack message with blocks support."""

    text: str
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    channel: Optional[str] = None
    username: str = "Raze Logger"
    icon_emoji: str = ":zap:"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Slack webhook payload."""
        payload: Dict[str, Any] = {
            "text": self.text,
            "username": self.username,
            "icon_emoji": self.icon_emoji,
        }
        if self.blocks:
            payload["blocks"] = self.blocks
        if self.channel:
            payload["channel"] = self.channel
        return payload


@dataclass
class SlackAlertRule:
    """Rule for filtering which events trigger Slack alerts."""

    name: str
    min_level: str = "warning"
    event_types: Optional[List[str]] = None  # Filter by event type
    fields_match: Optional[Dict[str, Any]] = None  # Match specific field values
    rate_limit_seconds: float = 60.0  # Throttle similar alerts

    def matches(self, event: LogEvent) -> bool:
        """Check if an event matches this rule."""
        # Check level threshold
        event_priority = LOG_LEVEL_PRIORITY.get(event.level.lower(), 1)
        min_priority = LOG_LEVEL_PRIORITY.get(self.min_level.lower(), 2)
        if event_priority < min_priority:
            return False

        # Check event type filter
        if self.event_types:
            if event.event_type not in self.event_types:
                return False

        # Check field matches
        if self.fields_match:
            for field_name, expected_value in self.fields_match.items():
                actual_value = event.fields.get(field_name)
                if actual_value != expected_value:
                    return False

        return True


class SlackSink(RazeSink):
    """Slack sink for log alerting.

    Sends log events to Slack webhooks based on configurable rules.
    Supports rate limiting, batching, and rich message formatting.

    Features:
    - Level-based filtering (warning, error, critical)
    - Event type filtering
    - Rate limiting to prevent alert fatigue
    - Rich message formatting with Slack blocks
    - Async sending with background thread
    - Batch aggregation for bursts

    Example:
        # Simple webhook configuration
        sink = SlackSink(
            webhook_url="https://hooks.slack.com/services/XXX",
            min_level="error",
        )

        # With custom rules
        sink = SlackSink(
            webhook_url="https://hooks.slack.com/services/XXX",
            rules=[
                SlackAlertRule(
                    name="cost_alerts",
                    min_level="warning",
                    event_types=["cost_exceeded", "budget_warning"],
                    rate_limit_seconds=300,  # 5 min
                ),
                SlackAlertRule(
                    name="training_failures",
                    min_level="error",
                    event_types=["training_job_failed"],
                ),
            ],
        )
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        channel: Optional[str] = None,
        min_level: str = "warning",
        rules: Optional[List[SlackAlertRule]] = None,
        batch_window_seconds: float = 5.0,
        max_batch_size: int = 10,
        rate_limit_seconds: float = 60.0,
        username: str = "Raze Logger",
        icon_emoji: str = ":zap:",
        format_fn: Optional[Callable[[LogEvent], SlackMessage]] = None,
    ) -> None:
        """Initialize Slack sink.

        Args:
            webhook_url: Slack incoming webhook URL.
            channel: Override channel (optional, uses webhook default).
            min_level: Minimum log level to send (debug, info, warning, error, critical).
            rules: Custom alert rules (overrides min_level if provided).
            batch_window_seconds: Window for batching similar events.
            max_batch_size: Maximum events per batch message.
            rate_limit_seconds: Default rate limit between similar events.
            username: Slack bot username.
            icon_emoji: Slack bot emoji.
            format_fn: Custom function to format events as SlackMessage.
        """
        self._webhook_url = webhook_url
        self._channel = channel
        self._min_level = min_level
        self._batch_window = batch_window_seconds
        self._max_batch_size = max_batch_size
        self._rate_limit = rate_limit_seconds
        self._username = username
        self._icon_emoji = icon_emoji
        self._format_fn = format_fn

        # Default rule if none provided
        if rules:
            self._rules = rules
        else:
            self._rules = [
                SlackAlertRule(
                    name="default",
                    min_level=min_level,
                    rate_limit_seconds=rate_limit_seconds,
                )
            ]

        # Rate limiting state
        self._last_sent: Dict[str, float] = {}  # Key -> timestamp
        self._lock = threading.Lock()

        # Async sending queue
        self._queue: Queue[LogEvent] = Queue()
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="raze-slack-sink",
            daemon=True,
        )
        self._worker.start()

    def write(self, event: LogEvent) -> None:
        """Queue a single log event for sending."""
        if self._should_alert(event):
            self._queue.put(event)

    def write_batch(self, events: List[LogEvent]) -> None:
        """Queue a batch of log events."""
        for event in events:
            self.write(event)

    def flush(self) -> None:
        """Flush queued events."""
        # Wait for queue to drain
        self._queue.join()

    def close(self) -> None:
        """Stop worker thread and close sink."""
        self._running = False
        self._worker.join(timeout=5.0)

    def query(self, request: LogQueryRequest) -> Tuple[List[LogEvent], int]:
        """Query is not supported for Slack sink."""
        raise NotImplementedError(
            "Query not supported for Slack sink. "
            "Slack is an alert destination, not a storage backend."
        )

    def aggregate(self, request: LogAggregateRequest) -> Tuple[List[LogAggregation], int]:
        """Aggregation is not supported for Slack sink."""
        raise NotImplementedError(
            "Aggregation not supported for Slack sink. "
            "Slack is an alert destination, not a storage backend."
        )

    def _should_alert(self, event: LogEvent) -> bool:
        """Check if event should trigger a Slack alert."""
        for rule in self._rules:
            if rule.matches(event):
                # Check rate limit
                rate_key = self._get_rate_limit_key(event, rule)
                with self._lock:
                    last_time = self._last_sent.get(rate_key, 0)
                    now = time.time()
                    if now - last_time >= rule.rate_limit_seconds:
                        self._last_sent[rate_key] = now
                        return True
                    else:
                        logger.debug(
                            "Rate limited Slack alert: %s (%.1fs remaining)",
                            rate_key,
                            rule.rate_limit_seconds - (now - last_time),
                        )
                        return False
        return False

    def _get_rate_limit_key(self, event: LogEvent, rule: SlackAlertRule) -> str:
        """Generate rate limit key for deduplication."""
        return f"{rule.name}:{event.event_type}:{event.level}"

    def _worker_loop(self) -> None:
        """Background worker for sending Slack messages."""
        while self._running:
            try:
                # Collect events within batch window
                batch: List[LogEvent] = []
                try:
                    event = self._queue.get(timeout=self._batch_window)
                    batch.append(event)
                    self._queue.task_done()

                    # Collect more events within window
                    deadline = time.time() + self._batch_window
                    while len(batch) < self._max_batch_size and time.time() < deadline:
                        try:
                            event = self._queue.get(timeout=0.1)
                            batch.append(event)
                            self._queue.task_done()
                        except Empty:
                            break

                except Empty:
                    continue

                if batch:
                    self._send_batch(batch)

            except Exception as e:
                logger.exception("Error in Slack sink worker: %s", e)

    def _send_batch(self, events: List[LogEvent]) -> None:
        """Send a batch of events to Slack."""
        try:
            import urllib.request
            import urllib.error

            if len(events) == 1:
                message = self._format_event(events[0])
            else:
                message = self._format_batch(events)

            payload = json.dumps(message.to_dict()).encode("utf-8")

            req = urllib.request.Request(
                self._webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    logger.warning(
                        "Slack webhook returned %d: %s",
                        response.status,
                        response.read().decode(),
                    )

        except urllib.error.URLError as e:
            logger.error("Failed to send Slack alert: %s", e)
        except Exception as e:
            logger.exception("Unexpected error sending Slack alert: %s", e)

    def _format_event(self, event: LogEvent) -> SlackMessage:
        """Format a single event as a Slack message."""
        if self._format_fn:
            return self._format_fn(event)

        # Default formatting with blocks
        level_emoji = {
            "debug": "🔍",
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }.get(event.level.lower(), "📋")

        level_color = {
            "debug": "#808080",
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "critical": "#9C27B0",
        }.get(event.level.lower(), "#808080")

        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{level_emoji} {event.event_type}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": event.message,
                },
            },
        ]

        # Add context fields
        context_elements: List[Dict[str, Any]] = [
            {"type": "mrkdwn", "text": f"*Level:* {event.level}"},
            {"type": "mrkdwn", "text": f"*Source:* {event.source}"},
            {"type": "mrkdwn", "text": f"*Time:* {event.timestamp.isoformat()}"},
        ]

        if event.run_id:
            context_elements.append({"type": "mrkdwn", "text": f"*Run ID:* `{event.run_id}`"})

        blocks.append({
            "type": "context",
            "elements": context_elements,
        })

        # Add important fields
        if event.fields:
            important_fields = ["error", "cost_usd", "job_id", "model_id", "trained_tokens"]
            field_text = []
            for key in important_fields:
                if key in event.fields:
                    field_text.append(f"• *{key}:* `{event.fields[key]}`")

            if field_text:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(field_text),
                    },
                })

        return SlackMessage(
            text=f"[{event.level.upper()}] {event.event_type}: {event.message[:100]}",
            blocks=blocks,
            channel=self._channel,
            username=self._username,
            icon_emoji=self._icon_emoji,
        )

    def _format_batch(self, events: List[LogEvent]) -> SlackMessage:
        """Format multiple events as a single Slack message."""
        # Group by event type
        by_type: Dict[str, List[LogEvent]] = {}
        for event in events:
            by_type.setdefault(event.event_type, []).append(event)

        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📊 {len(events)} Events",
                    "emoji": True,
                },
            },
        ]

        for event_type, type_events in by_type.items():
            highest_level = max(
                type_events,
                key=lambda e: LOG_LEVEL_PRIORITY.get(e.level.lower(), 0)
            ).level

            level_emoji = {
                "warning": "⚠️",
                "error": "❌",
                "critical": "🚨",
            }.get(highest_level.lower(), "📋")

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{level_emoji} *{event_type}* ({len(type_events)} events)",
                },
            })

            # Show first few messages
            for event in type_events[:3]:
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"• {event.message[:100]}"},
                    ],
                })

            if len(type_events) > 3:
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"_...and {len(type_events) - 3} more_"},
                    ],
                })

        return SlackMessage(
            text=f"{len(events)} log events",
            blocks=blocks,
            channel=self._channel,
            username=self._username,
            icon_emoji=self._icon_emoji,
        )


# Convenience factory for cost alerting
def create_cost_alert_sink(
    webhook_url: str,
    *,
    channel: Optional[str] = None,
    cost_threshold_usd: float = 10.0,
    rate_limit_minutes: float = 15.0,
) -> SlackSink:
    """Create a SlackSink configured for cost alerting.

    Args:
        webhook_url: Slack webhook URL.
        channel: Override channel (optional).
        cost_threshold_usd: Alert when cost exceeds this threshold.
        rate_limit_minutes: Minutes between similar alerts.

    Returns:
        Configured SlackSink for cost alerts.

    Example:
        from raze.sinks.slack import create_cost_alert_sink

        cost_sink = create_cost_alert_sink(
            webhook_url="https://hooks.slack.com/services/XXX",
            channel="#billing-alerts",
            cost_threshold_usd=50.0,
        )
    """
    def format_cost_event(event: LogEvent) -> SlackMessage:
        cost = event.fields.get("cost_usd", 0)
        job_id = event.fields.get("job_id", "unknown")
        model = event.fields.get("model", "unknown")
        tokens = event.fields.get("trained_tokens", 0)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "💰 Training Cost Alert",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Cost:*\n${cost:.2f} USD"},
                    {"type": "mrkdwn", "text": f"*Job ID:*\n`{job_id}`"},
                    {"type": "mrkdwn", "text": f"*Model:*\n{model}"},
                    {"type": "mrkdwn", "text": f"*Tokens:*\n{tokens:,}"},
                ],
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"⏰ {event.timestamp.isoformat()}"},
                ],
            },
        ]

        return SlackMessage(
            text=f"Training cost alert: ${cost:.2f} for job {job_id}",
            blocks=blocks,
            channel=channel,
            username="Midnighter Cost Monitor",
            icon_emoji=":money_with_wings:",
        )

    return SlackSink(
        webhook_url=webhook_url,
        channel=channel,
        rules=[
            SlackAlertRule(
                name="cost_exceeded",
                min_level="warning",
                event_types=[
                    "training_cost",
                    "cost_exceeded",
                    "budget_warning",
                    "training_job_completed",
                ],
                rate_limit_seconds=rate_limit_minutes * 60,
            ),
        ],
        format_fn=format_cost_event,
        username="Midnighter Cost Monitor",
        icon_emoji=":money_with_wings:",
    )
