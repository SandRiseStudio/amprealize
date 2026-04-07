"""Raze integration for Midnighter cost tracking and alerting.

Provides structured logging and Slack alerting for training costs using Raze.

Example:
    from mdnt.integrations.raze_integration import create_raze_hooks

    hooks = create_raze_hooks(
        slack_webhook_url="https://hooks.slack.com/services/XXX",
        slack_channel="#ml-costs",
        cost_threshold_usd=25.0,
    )

    service = MidnighterService(hooks=hooks)

    # Now all training jobs will:
    # 1. Log costs to Raze with structured fields
    # 2. Alert to Slack when costs exceed threshold
    # 3. Emit metrics for dashboards
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# Lazy import check for Raze
def _check_raze_available() -> bool:
    """Check if Raze is installed."""
    try:
        import raze
        return True
    except ImportError:
        return False


@dataclass
class CostRecord:
    """Record of a training cost event."""

    job_id: str
    cost_usd: float
    trained_tokens: int
    model: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class RazeCostTracker:
    """Track training costs with Raze logging and optional Slack alerts.

    This class wraps Raze's logging functionality to provide:
    - Structured cost logging with all relevant fields
    - Threshold-based Slack alerts via SlackSink
    - Cost aggregation and reporting
    - Integration with Midnighter hooks

    Attributes:
        total_cost_usd: Running total of all tracked costs.
        cost_records: List of all cost events.

    Example:
        tracker = RazeCostTracker(
            slack_webhook_url="https://hooks.slack.com/services/XXX",
            cost_threshold_usd=50.0,
            source="midnighter-training",
        )

        # Track a cost event
        tracker.record_cost(
            job_id="ftjob-abc123",
            cost_usd=12.50,
            trained_tokens=1_000_000,
            model="gpt-4o-mini-2024-07-18",
        )

        # Get summary
        print(f"Total cost: ${tracker.total_cost_usd:.2f}")
    """

    def __init__(
        self,
        *,
        slack_webhook_url: Optional[str] = None,
        slack_channel: Optional[str] = None,
        cost_threshold_usd: float = 25.0,
        alert_rate_limit_minutes: float = 15.0,
        source: str = "midnighter",
        raze_logger: Optional[Any] = None,
    ) -> None:
        """Initialize the cost tracker.

        Args:
            slack_webhook_url: Slack webhook for cost alerts (optional).
            slack_channel: Override Slack channel (optional).
            cost_threshold_usd: Alert when single job cost exceeds this.
            alert_rate_limit_minutes: Rate limit between similar alerts.
            source: Source identifier for log events.
            raze_logger: Existing RazeLogger instance (optional).
        """
        self._source = source
        self._cost_threshold = cost_threshold_usd
        self._cost_records: List[CostRecord] = []
        self._total_cost_usd = 0.0

        # Initialize Raze if available
        self._raze_logger = raze_logger
        self._slack_sink = None

        if _check_raze_available():
            self._setup_raze(
                slack_webhook_url=slack_webhook_url,
                slack_channel=slack_channel,
                alert_rate_limit_minutes=alert_rate_limit_minutes,
            )
        else:
            logger.warning(
                "Raze not installed. Cost tracking will use basic logging. "
                "Install with: pip install raze"
            )

    def _setup_raze(
        self,
        slack_webhook_url: Optional[str],
        slack_channel: Optional[str],
        alert_rate_limit_minutes: float,
    ) -> None:
        """Set up Raze logging and Slack sink."""
        try:
            from raze import RazeLogger
            from raze.sinks import InMemorySink

            # Create logger if not provided
            if self._raze_logger is None:
                self._raze_logger = RazeLogger(
                    source=self._source,
                    sink=InMemorySink(),  # Default to in-memory
                )

            # Add Slack sink if webhook provided
            if slack_webhook_url:
                try:
                    from raze.sinks.slack import create_cost_alert_sink

                    self._slack_sink = create_cost_alert_sink(
                        webhook_url=slack_webhook_url,
                        channel=slack_channel,
                        cost_threshold_usd=self._cost_threshold,
                        rate_limit_minutes=alert_rate_limit_minutes,
                    )
                    logger.info(
                        "Slack cost alerts enabled (threshold: $%.2f)",
                        self._cost_threshold,
                    )
                except ImportError:
                    logger.warning(
                        "Slack sink not available. Install with: pip install raze[slack]"
                    )

        except Exception as e:
            logger.error("Failed to set up Raze integration: %s", e)

    @property
    def total_cost_usd(self) -> float:
        """Get total cost tracked so far."""
        return self._total_cost_usd

    @property
    def cost_records(self) -> List[CostRecord]:
        """Get all cost records."""
        return list(self._cost_records)

    def record_cost(
        self,
        job_id: str,
        cost_usd: float,
        trained_tokens: int,
        model: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a training cost event.

        Logs to Raze with structured fields and sends Slack alert
        if cost exceeds threshold.

        Args:
            job_id: Fine-tuning job ID.
            cost_usd: Cost in USD.
            trained_tokens: Number of tokens trained.
            model: Base model used.
            metadata: Additional metadata (optional).
        """
        record = CostRecord(
            job_id=job_id,
            cost_usd=cost_usd,
            trained_tokens=trained_tokens,
            model=model,
            metadata=metadata or {},
        )

        self._cost_records.append(record)
        self._total_cost_usd += cost_usd

        # Determine log level based on threshold
        level = "warning" if cost_usd >= self._cost_threshold else "info"

        # Build log event fields
        fields = {
            "job_id": job_id,
            "cost_usd": cost_usd,
            "trained_tokens": trained_tokens,
            "model": model,
            "total_cost_usd": self._total_cost_usd,
            **(metadata or {}),
        }

        # Log with Raze if available
        if self._raze_logger:
            try:
                from raze.models import LogEvent

                event = LogEvent(
                    event_type="training_cost",
                    source=self._source,
                    level=level,
                    message=f"Training cost: ${cost_usd:.2f} for job {job_id}",
                    timestamp=record.timestamp,
                    fields=fields,
                )

                # Write to primary logger
                self._raze_logger.log_event(event)

                # Also write to Slack sink if configured
                if self._slack_sink:
                    self._slack_sink.write(event)

            except Exception as e:
                logger.error("Failed to log cost event to Raze: %s", e)
        else:
            # Fallback to standard logging
            log_fn = logger.warning if level == "warning" else logger.info
            log_fn(
                "Training cost: $%.2f for job %s (tokens: %d, model: %s)",
                cost_usd,
                job_id,
                trained_tokens,
                model,
            )

    def get_callback(
        self,
    ) -> Callable[[str, float, int, str, Optional[Dict[str, Any]]], None]:
        """Get a callback function for use with MidnighterHooks.

        Returns:
            Callback function compatible with on_cost hook.

        Example:
            tracker = RazeCostTracker(...)
            hooks = MidnighterHooks(on_cost=tracker.get_callback())
        """
        return self.record_cost

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all tracked costs.

        Returns:
            Dictionary with cost statistics.
        """
        if not self._cost_records:
            return {
                "total_cost_usd": 0.0,
                "job_count": 0,
                "total_tokens": 0,
                "average_cost_per_job": 0.0,
            }

        return {
            "total_cost_usd": self._total_cost_usd,
            "job_count": len(self._cost_records),
            "total_tokens": sum(r.trained_tokens for r in self._cost_records),
            "average_cost_per_job": self._total_cost_usd / len(self._cost_records),
            "by_model": self._group_by_model(),
        }

    def _group_by_model(self) -> Dict[str, Dict[str, Any]]:
        """Group costs by model."""
        by_model: Dict[str, Dict[str, Any]] = {}

        for record in self._cost_records:
            if record.model not in by_model:
                by_model[record.model] = {
                    "cost_usd": 0.0,
                    "job_count": 0,
                    "total_tokens": 0,
                }

            by_model[record.model]["cost_usd"] += record.cost_usd
            by_model[record.model]["job_count"] += 1
            by_model[record.model]["total_tokens"] += record.trained_tokens

        return by_model

    def close(self) -> None:
        """Close the cost tracker and flush any pending alerts."""
        if self._slack_sink:
            try:
                self._slack_sink.flush()
                self._slack_sink.close()
            except Exception as e:
                logger.error("Error closing Slack sink: %s", e)


def create_cost_callback(
    *,
    slack_webhook_url: Optional[str] = None,
    slack_channel: Optional[str] = None,
    cost_threshold_usd: float = 25.0,
    source: str = "midnighter",
) -> Callable[[str, float, int, str, Optional[Dict[str, Any]]], None]:
    """Create a cost callback function for MidnighterHooks.

    Convenience function that creates a RazeCostTracker and returns
    its callback for direct use with hooks.

    Args:
        slack_webhook_url: Slack webhook for alerts (optional).
        slack_channel: Override Slack channel (optional).
        cost_threshold_usd: Alert threshold in USD.
        source: Source identifier for logs.

    Returns:
        Callback function for on_cost hook.

    Example:
        from mdnt.integrations import create_cost_callback

        hooks = MidnighterHooks(
            on_cost=create_cost_callback(
                slack_webhook_url="https://hooks.slack.com/services/XXX",
                cost_threshold_usd=50.0,
            ),
        )
    """
    tracker = RazeCostTracker(
        slack_webhook_url=slack_webhook_url,
        slack_channel=slack_channel,
        cost_threshold_usd=cost_threshold_usd,
        source=source,
    )
    return tracker.get_callback()


def create_raze_hooks(
    *,
    slack_webhook_url: Optional[str] = None,
    slack_channel: Optional[str] = None,
    cost_threshold_usd: float = 25.0,
    source: str = "midnighter",
) -> "MidnighterHooks":
    """Create MidnighterHooks with Raze integration.

    Convenience function that creates hooks pre-configured with
    Raze logging and optional Slack cost alerts.

    Args:
        slack_webhook_url: Slack webhook for cost alerts (optional).
        slack_channel: Override Slack channel (optional).
        cost_threshold_usd: Alert when cost exceeds this threshold.
        source: Source identifier for Raze logs.

    Returns:
        MidnighterHooks instance with cost tracking configured.

    Example:
        from mdnt.integrations import create_raze_hooks

        hooks = create_raze_hooks(
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            cost_threshold_usd=100.0,
        )

        service = MidnighterService(hooks=hooks)
    """
    from mdnt.hooks import MidnighterHooks

    tracker = RazeCostTracker(
        slack_webhook_url=slack_webhook_url,
        slack_channel=slack_channel,
        cost_threshold_usd=cost_threshold_usd,
        source=source,
    )

    # Create metric callback that logs to Raze
    def on_metric(event_type: str, data: Dict[str, Any]) -> None:
        if tracker._raze_logger:
            try:
                from raze.models import LogEvent

                event = LogEvent(
                    event_type=event_type,
                    source=source,
                    level="info",
                    message=f"Metric: {event_type}",
                    fields=data,
                )
                tracker._raze_logger.log_event(event)
            except Exception as e:
                logger.debug("Failed to log metric to Raze: %s", e)

    # Create action callback that logs to Raze
    def on_action(action_type: str, payload: Dict[str, Any]) -> None:
        if tracker._raze_logger:
            try:
                from raze.models import LogEvent

                event = LogEvent(
                    event_type=f"action.{action_type}",
                    source=source,
                    level="info",
                    message=f"Action: {action_type}",
                    fields=payload,
                )
                tracker._raze_logger.log_event(event)
            except Exception as e:
                logger.debug("Failed to log action to Raze: %s", e)

    return MidnighterHooks(
        on_cost=tracker.get_callback(),
        on_metric=on_metric,
        on_action=on_action,
    )
