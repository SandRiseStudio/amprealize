"""Tests for BreakerAmpHooks."""

import pytest
from typing import Any, Dict

from breakeramp import BreakerAmpHooks


class TestBreakerAmpHooks:
    """Tests for BreakerAmpHooks dataclass."""

    def test_default_hooks_are_noop(self):
        """Default hooks are no-op functions."""
        hooks = BreakerAmpHooks()

        # on_action should return a string (action ID)
        action_id = hooks.on_action("test.action", {"key": "value"})
        assert isinstance(action_id, str)
        assert action_id.startswith("amp-")

        # on_compliance_step should not raise
        hooks.on_compliance_step("test.step", {"key": "value"})

        # on_metric should not raise
        hooks.on_metric("test.metric", {"value": 42})

    def test_custom_action_hook(self):
        """Can provide custom action hook."""
        recorded = []

        def custom_action(action_type: str, details: Dict[str, Any]) -> str:
            recorded.append((action_type, details))
            return f"custom-{len(recorded)}"

        hooks = BreakerAmpHooks(on_action=custom_action)

        result = hooks.on_action("my.action", {"foo": "bar"})

        assert result == "custom-1"
        assert len(recorded) == 1
        assert recorded[0] == ("my.action", {"foo": "bar"})

    def test_custom_compliance_hook(self):
        """Can provide custom compliance hook."""
        recorded = []

        def custom_compliance(step_type: str, details: Dict[str, Any]) -> None:
            recorded.append((step_type, details))

        hooks = BreakerAmpHooks(on_compliance_step=custom_compliance)

        hooks.on_compliance_step("resource.allocated", {"resource": "container"})

        assert len(recorded) == 1
        assert recorded[0][0] == "resource.allocated"

    def test_custom_metric_hook(self):
        """Can provide custom metric hook."""
        recorded = []

        def custom_metric(event_name: str, payload: Dict[str, Any]) -> None:
            recorded.append((event_name, payload))

        hooks = BreakerAmpHooks(on_metric=custom_metric)

        hooks.on_metric("breakeramp.boot.duration", {"duration_ms": 1500})

        assert len(recorded) == 1
        assert recorded[0][0] == "breakeramp.boot.duration"
        assert recorded[0][1]["duration_ms"] == 1500

    def test_all_custom_hooks(self):
        """Can provide all custom hooks together."""
        actions = []
        compliance = []
        metrics = []

        hooks = BreakerAmpHooks(
            on_action=lambda t, d: (actions.append((t, d)), f"act-{len(actions)}")[1],
            on_compliance_step=lambda t, d: compliance.append((t, d)),
            on_metric=lambda n, p: metrics.append((n, p)),
        )

        hooks.on_action("test.action", {})
        hooks.on_compliance_step("test.step", {})
        hooks.on_metric("test.metric", {})

        assert len(actions) == 1
        assert len(compliance) == 1
        assert len(metrics) == 1

    def test_hooks_are_independent(self):
        """Hooks don't interfere with each other."""
        action_calls = 0

        def counting_action(action_type: str, details: Dict[str, Any]) -> str:
            nonlocal action_calls
            action_calls += 1
            return f"action-{action_calls}"

        hooks = BreakerAmpHooks(on_action=counting_action)

        # Call multiple times
        hooks.on_action("first", {})
        hooks.on_action("second", {})
        hooks.on_action("third", {})

        assert action_calls == 3

        # Default compliance/metric hooks should still work
        hooks.on_compliance_step("step", {})
        hooks.on_metric("metric", {})

        # Action count unchanged
        assert action_calls == 3
