"""Integrations for Midnighter with external services.

This module provides ready-to-use integrations with:
- Raze: Structured logging and cost alerting
- Amprealize: BehaviorService, ActionService integration

Example:
    from mdnt.integrations import create_raze_hooks

    hooks = create_raze_hooks(
        slack_webhook_url="https://hooks.slack.com/services/XXX",
        cost_threshold_usd=50.0,
    )

    service = MidnighterService(hooks=hooks)
"""

from mdnt.integrations.raze_integration import (
    create_raze_hooks,
    RazeCostTracker,
    create_cost_callback,
)

__all__ = [
    "create_raze_hooks",
    "RazeCostTracker",
    "create_cost_callback",
]
