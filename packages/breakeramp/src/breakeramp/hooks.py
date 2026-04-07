"""Hooks for integrating BreakerAmp with external services.

The BreakerAmpHooks dataclass provides callback points for:
- Action tracking (audit trails, external action services)
- Compliance step recording
- Metrics/telemetry emission

This allows BreakerAmp to remain standalone while enabling rich
integrations when used within larger platforms like Amprealize.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Protocol


class ActionCallback(Protocol):
    """Protocol for action tracking callbacks.

    Called when BreakerAmp performs significant operations that should
    be tracked (plan, apply, destroy, etc.).

    Args:
        action_type: Type of action (e.g., "breakeramp.plan", "breakeramp.apply")
        details: Dictionary with action details (plan_id, environment, etc.)

    Returns:
        Action ID for tracking (can be used in subsequent callbacks)
    """
    def __call__(self, action_type: str, details: Dict[str, Any]) -> str: ...


class ComplianceCallback(Protocol):
    """Protocol for compliance step recording callbacks.

    Called during operations that have compliance implications
    (resource allocation, teardown, etc.).

    Args:
        step_type: Type of compliance step (e.g., "environment_planned", "resource_allocated")
        details: Dictionary with step details
    """
    def __call__(self, step_type: str, details: Dict[str, Any]) -> None: ...


class MetricCallback(Protocol):
    """Protocol for metrics/telemetry callbacks.

    Called for telemetry events that might feed dashboards or analytics.

    Args:
        event_name: Name of the metric event (e.g., "breakeramp.runtime.resource_ok")
        payload: Dictionary with metric data
    """
    def __call__(self, event_name: str, payload: Dict[str, Any]) -> None: ...


def _noop_action(action_type: str, details: Dict[str, Any]) -> str:
    """Default no-op action callback that returns a placeholder ID."""
    import uuid
    return f"amp-{uuid.uuid4().hex[:12]}"


def _noop_compliance(step_type: str, details: Dict[str, Any]) -> None:
    """Default no-op compliance callback."""
    pass


def _noop_metric(event_name: str, payload: Dict[str, Any]) -> None:
    """Default no-op metric callback."""
    pass


@dataclass
class BreakerAmpHooks:
    """Hooks for integrating BreakerAmp with external services.

    All hooks have sensible defaults (no-ops) so BreakerAmp can run
    standalone without any external dependencies.

    Example:
        # Standalone usage (no hooks needed)
        service = BreakerAmpService(executor=executor)

        # With custom hooks
        def my_action_handler(action_type: str, details: dict) -> str:
            # Log to external system
            return log_action(action_type, details)

        hooks = BreakerAmpHooks(on_action=my_action_handler)
        service = BreakerAmpService(executor=executor, hooks=hooks)

    Attributes:
        on_action: Called when significant operations occur. Should return
                   an action ID for tracking.
        on_compliance_step: Called for compliance/audit trail entries.
        on_metric: Called for telemetry/metrics events.
    """

    on_action: Callable[[str, Dict[str, Any]], str] = field(default=_noop_action)
    on_compliance_step: Callable[[str, Dict[str, Any]], None] = field(default=_noop_compliance)
    on_metric: Callable[[str, Dict[str, Any]], None] = field(default=_noop_metric)

    def record_action(self, action_type: str, **details: Any) -> str:
        """Record an action and return its ID.

        Convenience method that calls on_action with the given details.
        """
        return self.on_action(action_type, details)

    def record_compliance_step(self, step_type: str, **details: Any) -> None:
        """Record a compliance step.

        Convenience method that calls on_compliance_step with the given details.
        """
        self.on_compliance_step(step_type, details)

    def emit_metric(self, event_name: str, **payload: Any) -> None:
        """Emit a metric event.

        Convenience method that calls on_metric with the given payload.
        """
        self.on_metric(event_name, payload)
